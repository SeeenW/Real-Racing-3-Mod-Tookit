#if defined(CUBEMAP_TO_SPHERICAL)

uniform lowp samplerCube s_Texture0;
varying highp vec2 v_TexCoord0;

void main()
{
	highp float Ny = max(0.0, 1.0 - v_TexCoord0.x*v_TexCoord0.x - v_TexCoord0.y*v_TexCoord0.y);
	highp vec3 N = vec3(v_TexCoord0.x, sqrt(Ny), v_TexCoord0.y);
	highp vec3 R = reflect(vec3(0,1,0), N);
	//highp float K = max(0.0, dot(R, vec3(0,1,0)));
	//gl_FragColor = vec4(mix(textureCube(s_Texture0, R).rgb, vec3(0.0), K), 1.0);
	gl_FragColor = vec4(textureCube(s_Texture0, R).rgb, 1.0);
}

#endif

#if defined(SPHERICAL_TO_CUBEMAP)

uniform lowp sampler2D s_Texture0;
varying highp vec3 v_CubeCoord;

void main()
{
	highp vec3 C = v_CubeCoord;
	C.xy = -C.xy;
	C.z = -C.z;

	highp vec3 N = normalize(normalize(C) + vec3(0.0,1.0,0.0));
	highp vec2 UV = vec2(N.x, N.z) * 0.5 + vec2(0.5);

	highp vec3 s = texture2D(s_Texture0, UV).rgb;
	gl_FragColor = vec4(s, 1.0);
}

#endif

#if defined(PASS_THROUGH)

uniform lowp samplerCube s_Texture0;
varying highp vec3 v_CubeCoord;

void main()
{
	highp vec3 s = textureCube(s_Texture0, v_CubeCoord).rgb;
	gl_FragColor = vec4(s, 1.0);
}

#endif


#if defined(BLUR_HORIZONTAL) || defined(BLUR_VERTICAL)

uniform lowp samplerCube s_Texture0;
uniform highp float u_PointSize; //inverse of texture dimensions

varying highp vec3 v_CubeCoord;
varying highp vec3 v_CubeDirX;
varying highp vec3 v_CubeDirY;

const highp float w11	= 1.0			/ 1048576.0;
const highp float w10 	= 20.0			/ 1048576.0;
const highp float w9 	= 190.0			/ 1048576.0;
const highp float w8 	= 1140.0		/ 1048576.0;
const highp float w7 	= 4845.0		/ 1048576.0;
const highp float w6 	= 15504.0		/ 1048576.0;
const highp float w5 	= 38760.0		/ 1048576.0;
const highp float w4 	= 77520.0		/ 1048576.0;
const highp float w3 	= 125970.0		/ 1048576.0;
const highp float w2 	= 167960.0		/ 1048576.0;
const highp float w1 	= 184756.0		/ 1048576.0;

highp vec3 sampleTexture(lowp samplerCube sTextureImage, highp vec3 vCubeCoord, highp float nOffset, highp float nWeight)
{
#if defined(BLUR_HORIZONTAL)
	highp vec3 coordPos = vCubeCoord + nOffset * v_CubeDirX;
	highp vec3 coordNeg = vCubeCoord - nOffset * v_CubeDirX;
#endif
#if defined(BLUR_VERTICAL)
	highp vec3 coordPos = vCubeCoord + nOffset * v_CubeDirY;
	highp vec3 coordNeg = vCubeCoord - nOffset * v_CubeDirY;
#endif

	highp vec3 vColor 	= textureCube( sTextureImage, coordPos).rgb * nWeight;
	vColor 				+= textureCube( sTextureImage, coordNeg).rgb * nWeight;
	return  vColor;
}

void main()
{
	highp float ONE_PIXEL 	= (2.0 * u_PointSize);
	highp float offset 		= ONE_PIXEL;

	highp vec3 s = textureCube(s_Texture0, v_CubeCoord).rgb * w1;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w2);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w3);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w4);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w5);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w6);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w7);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w8);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w9);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w10);
	offset += ONE_PIXEL;
	
	s += sampleTexture(s_Texture0, v_CubeCoord, offset, w11);
	
	gl_FragColor = vec4(s, 1.0);
}

#endif
