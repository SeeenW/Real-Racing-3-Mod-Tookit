//
//  opacity_from_luma.fsh
//
//  Created by jribaux on 2014-06-30.
//  Copyright EA 2014. All rights reserved.
//

uniform lowp vec4 u_CurrentColour;

uniform lowp sampler2D s_Texture0;
varying mediump vec2 v_TexCoord0;

void main()
{
	lowp vec4 color = u_CurrentColour;
	color.a *= texture2D( s_Texture0, v_TexCoord0 ).g;
	gl_FragColor = color;
}
