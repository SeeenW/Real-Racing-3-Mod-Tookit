//
//  alpha_texture.fsh
//
//  Created by jribaux.
//  Copyright EA 2012. All rights reserved.
//

uniform lowp sampler2D s_Texture0;
varying highp vec2 v_TexCoord0;

#ifdef BATCH_RENDER
	varying lowp vec4 v_VertexColour;
#else
	uniform lowp vec4 u_CurrentColour;
#endif

void main()
{
	lowp float alpha = texture2D( s_Texture0, v_TexCoord0 ).a;
	//gl_FragColor = vec4( vec3( alpha ), 1.0);
#ifdef BATCH_RENDER
	gl_FragColor = vec4( v_VertexColour.rgb, v_VertexColour.a * alpha );
#else
	gl_FragColor = vec4( u_CurrentColour.rgb, u_CurrentColour.a * alpha );
#endif
}

